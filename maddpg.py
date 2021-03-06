import torch
import torch.nn.functional as F

from config import Config
from ddpg_agent import Agent
from replay_buffer import ReplayBuffer


class MultiAgentDDPG():
    """Manage multi agents while interacting with the environment."""
    def __init__(self):
        super(MultiAgentDDPG, self).__init__()
        self.config = Config()
        self.agents = [Agent() for _ in range(self.config.num_agents)]
        self.buffer = ReplayBuffer()

    def act(self, state):
        actions = [agent.act(obs) \
                   for agent, obs in zip(self.agents, state)]
        return actions

    def actions_target(self, states):
        batch_size = self.config.batch_size
        num_agents = self.config.num_agents
        action_size = self.config.action_size
        with torch.no_grad():
            actions = torch.empty(
                (batch_size, num_agents, action_size),
                device=self.config.device)
            for idx, agent in enumerate(self.agents):
                actions[:,idx] = agent.actor_target(states[:,idx])
        return actions

    def actions_local(self, states, agent_id):
        batch_size = self.config.batch_size
        num_agents = self.config.num_agents
        action_size = self.config.action_size

        actions = torch.empty(
            (batch_size, num_agents, action_size),
            device=self.config.device)
        for idx, agent in enumerate(self.agents):
            action = agent.actor_local(states[:,idx])
            if not idx == agent_id:
                action.detach()
            actions[:,idx] = action
        return actions

    def store(self, state, actions, rewards, next_state):
        self.buffer.store(state, actions, rewards, next_state)

        if len(self.buffer) >= self.config.batch_size:
            self.learn()

    def learn(self):
        batch_size = self.config.batch_size
        for agent_id, agent in enumerate(self.agents):
            # sample a batch of experiences
            states, actions, rewards, next_states = self.buffer.sample()
            # stack the agents' variables to feed the networks
            obs = states.view(batch_size, -1)
            actions = actions.view(batch_size, -1)
            next_obs = next_states.view(batch_size, -1)
            # Consider only the rewards for this agent
            r = rewards[:,agent_id].unsqueeze_(1)

            ## Train the Critic network
            with torch.no_grad():
                next_actions = self.actions_target(next_states)
                next_actions = next_actions.view(batch_size, -1)
                next_q_val = agent.critic_target(next_obs, next_actions)
                y = r + self.config.gamma * next_q_val
            agent.critic_optimizer.zero_grad()
            q_value_predicted = agent.critic_local(obs, actions)
            loss = F.mse_loss(q_value_predicted, y)
            loss.backward()
            agent.critic_optimizer.step()

            ## Train the Actor network
            agent.actor_optimizer.zero_grad()
            actions_local = self.actions_local(states, agent_id)
            actions_local = actions_local.view(batch_size, -1)
            q_value_predicted = agent.critic_local(obs, actions_local)
            loss = -q_value_predicted.mean()
            loss.backward()
            agent.actor_optimizer.step()

        for agent in self.agents:
            agent.soft_update()

    def reset_noise(self):
        for agent in self.agents:
            agent.reset_noise()

    def state_dict(self):
        return [agent.actor_local.state_dict() for agent in self.agents]

    def load_state_dict(self, state_dicts):
        for agent, state_dict in zip(self.agents, state_dicts):
            agent.actor_local.load_state_dict(state_dict)

    def lr_step(self):
        for agent in self.agents:
            agent.lr_step()
